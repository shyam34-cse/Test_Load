(function ($) {
    "use strict";

    // Spinner
    var spinner = function () {
        setTimeout(function () {
            if ($('#spinner').length > 0) {
                $('#spinner').removeClass('show');
            }
        }, 1);
    };
    spinner();
    
    
    // Back to top button
    $(window).scroll(function () {
        if ($(this).scrollTop() > 300) {
            $('.back-to-top').fadeIn('slow');
        } else {
            $('.back-to-top').fadeOut('slow');
        }
    });
    $('.back-to-top').click(function () {
        $('html, body').animate({scrollTop: 0}, 1500, 'easeInOutExpo');
        return false;
    });


    // Sidebar Toggler
    $('.sidebar-toggler').click(function () {
        $('.sidebar, .content').toggleClass("open");
        return false;
    });


    // Progress Bar
    $('.pg-bar').waypoint(function () {
        $('.progress .progress-bar').each(function () {
            $(this).css("width", $(this).attr("aria-valuenow") + '%');
        });
    }, {offset: '80%'});


    // Calender
    $('#calender').datetimepicker({
        inline: true,
        format: 'L'
    });


    // Testimonials carousel
    $(".testimonial-carousel").owlCarousel({
        autoplay: true,
        smartSpeed: 1000,
        items: 1,
        dots: true,
        loop: true,
        nav : false
    });

    // //Data Status Chart
    // var ctx1 = $("#bar-chart").get(0).getContext("2d");
    // var myChart1 = new Chart(ctx1, {
    //     type: 'bar',  // 'horizontalBar' in Chart.js 2.x; use 'bar' with indexAxis in Chart.js 3.x or later
    //     data: {
    //         labels: [],
    //         datasets: [{
    //             backgroundColor: [
    //                 "rgba(0, 156, 255, 0.7)",
    //                 "rgba(0, 156, 255, 0.5)",
    //                 "rgba(0, 156, 255, 0.3)"
    //             ],
    //             data: [0, 0, 0] // Example data percentages for neutral, positive, negative
    //         }]
    //     },
    //     options: {
    //         indexAxis: 'y',  // Only for Chart.js 3.x or later, make sure this is set for horizontal bar charts
    //         responsive: true,
    //         scales: {
    //             x: {  // 'xAxes' in Chart.js 2.x
    //                 ticks: {
    //                     beginAtZero: true,
    //                     callback: function(value) {
    //                         return value + "%"; // Appends a '%' sign after each value on the x-axis
    //                     }
    //                 }
    //             }
    //         },
    //         plugins: {
    //         legend: {
    //             display: false  // Hides the legend
    //         }
    //     }
    //     }
    // });

    // Ingestion Status Chart
    var ctx2 = $("#ingestion_chart").get(0).getContext("2d");
    var myChart2 = new Chart(ctx2, {
        type: "pie",
        data: {
            labels: ['Read', 'In Progress', 'Failed'],
            // labels: [],
            datasets: [{
                backgroundColor: [
                    "rgba(0, 156, 255, 0.7)",
                    "rgba(255, 165, 0, 0.7)",
                    "rgba(255, 10, 10, 0.7)",
                    "rgba(0, 0, 255, 0.1)",
                ],
                data: [50,20,30]
            }]
        },
        options: {
            responsive: true,
            // plugins: {
            //     title: {
            //         display:true,
            //         text:'Data Awaited!',
            //         // position: 'bottom',
            //         color: '#000'
            //     }
            // }
        }
    });

    // Overall Readiness chart
    var ctx1 = $("#bar_file_chart").get(0).getContext("2d");
    var myChart1 = new Chart(ctx1, {
        type: 'bar',
        data: {
            labels: ['pdf'],
            datasets: [{
                backgroundColor: [
                    "rgba(0, 156, 255, 0.7)",
                    "rgba(156, 0, 255, 0.7)",
                    "rgba(0, 0, 255, 0.7)",
                    "rgba(0, 0, 255, 0.1)",
                ],
                maxBarThickness:20,
                data: [10]  // Start with empty data, which will be updated dynamically
            }]
        },
        options: {
            indexAxis: 'y',
            responsive: true,
            scales: {
                x: {
                    ticks: {
                        beginAtZero: true,
                        callback: function(value) {
                            return value; // Appends a '%' sign after each value on the x-axis
                        },
                    },
                }
            },
            plugins: {
                legend: {
                    display: false
                }
            }
        }
    });

    // Readiness Chart
    var ctx3 = $("#readiness_chart").get(0).getContext("2d");
    var myChart3 = new Chart(ctx3,{
        type: "pie",
        data: {
            labels: ['Total Readiness', 'Data Left'],
            datasets: [{
                backgroundColor: [
                    "rgba(0, 156, 255, 0.7)",
                    "rgba(156, 0, 255, 0.7)",
                    "rgba(0, 0, 255, 0.7)",
                    "rgba(0, 0, 255, 0.1)",
                ],
                borderWidth: 1,
                circumference: 180,
                rotation : 270,
                aspectRatio : 2,
                borderRadius:8,
                cutout: 95,
                data: [75,25]
            }]
        },
        options: {
            responsive: true,
            // aspectRatio : 1, 
            plugins: {
                legend: {
                    display: true
                }
            }
        }
    });



    function updateCharts() {
        fetch('/graph_update')
        .then(response => response.json())
        .then(data => {

            if (data.pie_chart) {
                var ingestion_data = JSON.parse(data.pie_chart);
                console.log(ingestion_data)
                myChart2.data.datasets[0].data = [
                    ingestion_data.data[0].values[0],
                    ingestion_data.data[0].values[1],
                    ingestion_data.data[0].values[2]
                ];
                myChart2.data.labels = ingestion_data.data[0].labels;
                myChart2.data.title = ingestion_data.layout.title.text;
                // myChart3.data.datasets[0].data = sentimentData;
                myChart2.update(ingestion_data);
            }

            if (data.bars) {
                // console.log("Data not received")
                var bar_file_data = JSON.parse(data.bars);
                // console.log('Data Parsed!')
                // console.log(bar_file_data)
                myChart1.data.datasets[0].data = bar_file_data.data[0].x;
                // myChart1.data.datasets[0].data = bar_file_data.data[0].x;
                myChart1.data.labels = bar_file_data.data[0].y;
                // myChart3.data.datasets[0].data = sentimentData;
                myChart1.update(bar_file_data);
            }

            if (data.gauge_auth) {
                // console.log("Data not received")
                var gauge_data = JSON.parse(data.gauge_auth);
                myChart3.data.datasets[0].data = [
                    gauge_data.data[0].x,
                    100 - gauge_data.data[0].x
                ]
                myChart3.update(gauge_data);
            }

        })
        .catch(error => console.error('Error updating charts:', error));
    }
    
    // Update charts every 2 seconds (adjust as needed)
    setInterval(updateCharts, 2000);
    // console.log('Hello')
    // Initial update
    updateCharts();
    
})(jQuery);

